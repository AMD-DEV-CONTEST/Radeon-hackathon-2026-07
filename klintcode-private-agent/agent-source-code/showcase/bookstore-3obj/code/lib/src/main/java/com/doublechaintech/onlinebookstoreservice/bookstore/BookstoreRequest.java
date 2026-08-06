package com.doublechaintech.onlinebookstoreservice.bookstore;

import com.doublechaintech.onlinebookstoreservice.Q;
import com.doublechaintech.onlinebookstoreservice.book.Book;
import com.doublechaintech.onlinebookstoreservice.book.BookRequest;
import com.doublechaintech.onlinebookstoreservice.bookcategory.BookCategory;
import com.doublechaintech.onlinebookstoreservice.bookcategory.BookCategoryRequest;
import io.teaql.core.AggrFunction;
import io.teaql.core.BaseRequest;
import io.teaql.core.PropertyReference;
import io.teaql.core.SearchCriteria;
import io.teaql.core.SubQuerySearchCriteria;
import io.teaql.core.criteria.Operator;
import io.teaql.core.criteria.TwoOperatorCriteria;
import java.time.LocalDateTime;
import java.util.Date;

public class BookstoreRequest<T extends Bookstore> extends BaseRequest<T> {

    /**
     * @deprecated AI agents and business code must use the generated Q facade
     *             instead of constructing request builders directly.
     */
    @Deprecated
    public BookstoreRequest(Class<T> returnType){
        super(returnType);
        selectId();
        selectVersion();
    }

    public BookstoreRequest<T> comment(String comment){
         super.internalComment(comment);
         return this;
    }

    // purpose() 继承自 BaseRequest，返回 ExecutableRequest（终结方法）

    public BookstoreRequest<T> returnType(Class<? extends T> returnType){
        super.setReturnType(returnType);
        return this;
    }

    public BookstoreRequest<T> enableAggregationCache(long cacheExpiredMillis){
        super.enableAggregationCache();
        super.aggregateCacheTime(cacheExpiredMillis);
        return this;
    }

    public BookstoreRequest<T> enableAggregationCache(){
        return enableAggregationCache(0l);
    }


    public BookstoreRequest<T> propagateAggregationCache(long cacheExpiredMillis){
        super.propagateAggregationCache(cacheExpiredMillis);
        return this;
    }

    public BookstoreRequest<T> appendSearchCriteria(SearchCriteria searchCriteria){
        return (BookstoreRequest<T>)super.appendSearchCriteria(searchCriteria);
    }

    public BookstoreRequest<T> filter(String property1, Operator operator, String property2){
        return appendSearchCriteria(new TwoOperatorCriteria(operator, new PropertyReference(property1), new PropertyReference(property2)));
    }


    public BookstoreRequest<T> matchingAnyOf(BookstoreRequest bookstore){
        super.internalMatchAny(bookstore);
        return this;
    }

    public BookstoreRequest<T> enhanceChildrenIfNeeded(){
        return this;
    }

    public BookstoreRequest<T> withDeletedRows(){
        super.withDeletedRows();
        return this;
    }

    public BookstoreRequest<T> deletedRowsOnly(){
        super.deletedRowsOnly();
        return this;
    }

    public BookstoreRequest<T> selectSelf(){
        super.selectSelf();
        return selectId().selectName().selectAddress().selectPhone().selectCreateTime().selectUpdateTime().selectVersion();
    }

    public BookstoreRequest<T> selectSelfFields(){
        return selectSelf();
    }

    public BookstoreRequest<T> selectAll(){
        super.selectAll();
        return selectId().selectName().selectAddress().selectPhone().selectCreateTime().selectUpdateTime().selectVersion();
    }

    public BookstoreRequest<T> selectChildren(){
        super.selectAny();
        selectBookList().selectBookCategoryList();
        return selectId().selectName().selectAddress().selectPhone().selectCreateTime().selectUpdateTime().selectVersion();
    }


    public BookstoreRequest<T> selectId(){
       selectProperty(Bookstore.ID_PROPERTY);
       return this;
    }

    /**
     * fill the id with customized rawSqlSegment, TEAQL uses ({rawSqlSegment} AS  id) to fetch id property.
     * @param rawSqlSegment  customized rawSqlSegment
     */




    public BookstoreRequest<T> unselectId(){
       unselectProperty(Bookstore.ID_PROPERTY);
       return this;
    }
    public BookstoreRequest<T> selectName(){
       selectProperty(Bookstore.NAME_PROPERTY);
       return this;
    }

    /**
     * fill the name with customized rawSqlSegment, TEAQL uses ({rawSqlSegment} AS  name) to fetch name property.
     * @param rawSqlSegment  customized rawSqlSegment
     */




    public BookstoreRequest<T> unselectName(){
       unselectProperty(Bookstore.NAME_PROPERTY);
       return this;
    }
    public BookstoreRequest<T> selectAddress(){
       selectProperty(Bookstore.ADDRESS_PROPERTY);
       return this;
    }

    /**
     * fill the address with customized rawSqlSegment, TEAQL uses ({rawSqlSegment} AS  address) to fetch address property.
     * @param rawSqlSegment  customized rawSqlSegment
     */




    public BookstoreRequest<T> unselectAddress(){
       unselectProperty(Bookstore.ADDRESS_PROPERTY);
       return this;
    }
    public BookstoreRequest<T> selectPhone(){
       selectProperty(Bookstore.PHONE_PROPERTY);
       return this;
    }

    /**
     * fill the phone with customized rawSqlSegment, TEAQL uses ({rawSqlSegment} AS  phone) to fetch phone property.
     * @param rawSqlSegment  customized rawSqlSegment
     */


    /**
     * fill the phone with customized aggrFunction, TEAQL uses ({aggrFunction}(phone) AS phone to fetch phone property.
     * @param aggrFunction  aggrFunction
     */
    public BookstoreRequest<T> selectPhone(AggrFunction aggrFunction){
       selectProperty(Bookstore.PHONE_PROPERTY, aggrFunction);
       return this;
    }


    public BookstoreRequest<T> unselectPhone(){
       unselectProperty(Bookstore.PHONE_PROPERTY);
       return this;
    }
    public BookstoreRequest<T> selectCreateTime(){
       selectProperty(Bookstore.CREATE_TIME_PROPERTY);
       return this;
    }

    /**
     * fill the createTime with customized rawSqlSegment, TEAQL uses ({rawSqlSegment} AS  createTime) to fetch createTime property.
     * @param rawSqlSegment  customized rawSqlSegment
     */




    public BookstoreRequest<T> unselectCreateTime(){
       unselectProperty(Bookstore.CREATE_TIME_PROPERTY);
       return this;
    }
    public BookstoreRequest<T> selectUpdateTime(){
       selectProperty(Bookstore.UPDATE_TIME_PROPERTY);
       return this;
    }

    /**
     * fill the updateTime with customized rawSqlSegment, TEAQL uses ({rawSqlSegment} AS  updateTime) to fetch updateTime property.
     * @param rawSqlSegment  customized rawSqlSegment
     */




    public BookstoreRequest<T> unselectUpdateTime(){
       unselectProperty(Bookstore.UPDATE_TIME_PROPERTY);
       return this;
    }
    public BookstoreRequest<T> selectVersion(){
       selectProperty(Bookstore.VERSION_PROPERTY);
       return this;
    }

    /**
     * fill the version with customized rawSqlSegment, TEAQL uses ({rawSqlSegment} AS  version) to fetch version property.
     * @param rawSqlSegment  customized rawSqlSegment
     */




    public BookstoreRequest<T> unselectVersion(){
       unselectProperty(Bookstore.VERSION_PROPERTY);
       return this;
    }
    public BookstoreRequest<T> selectBookList(){
       return selectBookListWith(Q.books().selectSelf());
    }

    public BookstoreRequest<T> selectBookListWith(BookRequest bookList){
       enhanceRelation(Bookstore.BOOK_LIST_PROPERTY, bookList);
       return this;
    }
    public BookstoreRequest<T> selectBookCategoryList(){
       return selectBookCategoryListWith(Q.bookCategories().selectSelf());
    }

    public BookstoreRequest<T> selectBookCategoryListWith(BookCategoryRequest bookCategoryList){
       enhanceRelation(Bookstore.BOOK_CATEGORY_LIST_PROPERTY, bookCategoryList);
       return this;
    }

    public BookstoreRequest<T> withId(Operator operator, Object... values){
       return appendSearchCriteria(createIdCriteria(operator, values));
    }

    public SearchCriteria createIdCriteria(Operator operator, Object... values) {
        return createBasicSearchCriteria(Bookstore.ID_PROPERTY, operator, values);
    }

    public BookstoreRequest<T> withIdIs(Long id){
       return withId(Operator.EQUAL, id);
    }
    public BookstoreRequest<T> withIdIn(Long... id){
       return withId(Operator.EQUAL, (Object[])id);
    }



    public BookstoreRequest<T> filterByName(String... name){
      if (name == null || name.length == 0) {
        throw new IllegalArgumentException("filterByName parameter name cannot be empty");
      }
      return appendSearchCriteria(createNameCriteria(Operator.EQUAL, (Object[])name));
    }

    public BookstoreRequest<T> withName(Operator operator, Object... values){
       return appendSearchCriteria(createNameCriteria(operator, values));
    }

    public BookstoreRequest<T> withNameIsUnknown(){
       return withName(Operator.IS_NULL);
    }

    public BookstoreRequest<T> withNameIsKnown(){
       return withName(Operator.IS_NOT_NULL);
    }

    public SearchCriteria createNameCriteria(Operator operator, Object... values) {
        return createBasicSearchCriteria(Bookstore.NAME_PROPERTY, operator, values);
    }

    public BookstoreRequest<T> withNameGreaterThan(String name){
       return withName(Operator.GREATER_THAN, name);
    }

    public BookstoreRequest<T> withNameGreaterThanOrEqualTo(String name){
       return withName(Operator.GREATER_THAN_OR_EQUAL, name);
    }

    public BookstoreRequest<T> withNameLessThan(String name){
       return withName(Operator.LESS_THAN, name);
    }

    public BookstoreRequest<T> withNameLessThanOrEqualTo(String name){
       return withName(Operator.LESS_THAN_OR_EQUAL, name);
    }

    public BookstoreRequest<T> withNameBetween(String startOfName, String endOfName){
       return withName(Operator.BETWEEN, startOfName, endOfName);
    }
    public BookstoreRequest<T> withNameStartingWith(String name){
       return withName(Operator.BEGIN_WITH, name);
    }
    public BookstoreRequest<T> withNameContaining(String name){
       return withName(Operator.CONTAIN, name);
    }

    public BookstoreRequest<T> withNameEndingWith(String name){
       return withName(Operator.END_WITH, name);
    }

    public BookstoreRequest<T> withNameIs(String name){
       return withName(Operator.EQUAL, name);
    }

    public BookstoreRequest<T> withNameSoundingLike(String name){
       return withName(Operator.SOUNDS_LIKE, name);
    }



    public BookstoreRequest<T> filterByAddress(String... address){
      if (address == null || address.length == 0) {
        throw new IllegalArgumentException("filterByAddress parameter address cannot be empty");
      }
      return appendSearchCriteria(createAddressCriteria(Operator.EQUAL, (Object[])address));
    }

    public BookstoreRequest<T> withAddress(Operator operator, Object... values){
       return appendSearchCriteria(createAddressCriteria(operator, values));
    }

    public BookstoreRequest<T> withAddressIsUnknown(){
       return withAddress(Operator.IS_NULL);
    }

    public BookstoreRequest<T> withAddressIsKnown(){
       return withAddress(Operator.IS_NOT_NULL);
    }

    public SearchCriteria createAddressCriteria(Operator operator, Object... values) {
        return createBasicSearchCriteria(Bookstore.ADDRESS_PROPERTY, operator, values);
    }

    public BookstoreRequest<T> withAddressGreaterThan(String address){
       return withAddress(Operator.GREATER_THAN, address);
    }

    public BookstoreRequest<T> withAddressGreaterThanOrEqualTo(String address){
       return withAddress(Operator.GREATER_THAN_OR_EQUAL, address);
    }

    public BookstoreRequest<T> withAddressLessThan(String address){
       return withAddress(Operator.LESS_THAN, address);
    }

    public BookstoreRequest<T> withAddressLessThanOrEqualTo(String address){
       return withAddress(Operator.LESS_THAN_OR_EQUAL, address);
    }

    public BookstoreRequest<T> withAddressBetween(String startOfAddress, String endOfAddress){
       return withAddress(Operator.BETWEEN, startOfAddress, endOfAddress);
    }
    public BookstoreRequest<T> withAddressStartingWith(String address){
       return withAddress(Operator.BEGIN_WITH, address);
    }
    public BookstoreRequest<T> withAddressContaining(String address){
       return withAddress(Operator.CONTAIN, address);
    }

    public BookstoreRequest<T> withAddressEndingWith(String address){
       return withAddress(Operator.END_WITH, address);
    }

    public BookstoreRequest<T> withAddressIs(String address){
       return withAddress(Operator.EQUAL, address);
    }

    public BookstoreRequest<T> withAddressSoundingLike(String address){
       return withAddress(Operator.SOUNDS_LIKE, address);
    }



    public BookstoreRequest<T> filterByPhone(Integer... phone){
      if (phone == null || phone.length == 0) {
        throw new IllegalArgumentException("filterByPhone parameter phone cannot be empty");
      }
      return appendSearchCriteria(createPhoneCriteria(Operator.EQUAL, (Object[])phone));
    }

    public BookstoreRequest<T> withPhone(Operator operator, Object... values){
       return appendSearchCriteria(createPhoneCriteria(operator, values));
    }

    public BookstoreRequest<T> withPhoneIsUnknown(){
       return withPhone(Operator.IS_NULL);
    }

    public BookstoreRequest<T> withPhoneIsKnown(){
       return withPhone(Operator.IS_NOT_NULL);
    }

    public SearchCriteria createPhoneCriteria(Operator operator, Object... values) {
        return createBasicSearchCriteria(Bookstore.PHONE_PROPERTY, operator, values);
    }

    public BookstoreRequest<T> withPhoneGreaterThan(Integer phone){
       return withPhone(Operator.GREATER_THAN, phone);
    }

    public BookstoreRequest<T> withPhoneGreaterThanOrEqualTo(Integer phone){
       return withPhone(Operator.GREATER_THAN_OR_EQUAL, phone);
    }

    public BookstoreRequest<T> withPhoneLessThan(Integer phone){
       return withPhone(Operator.LESS_THAN, phone);
    }

    public BookstoreRequest<T> withPhoneLessThanOrEqualTo(Integer phone){
       return withPhone(Operator.LESS_THAN_OR_EQUAL, phone);
    }

    public BookstoreRequest<T> withPhoneBetween(Integer startOfPhone, Integer endOfPhone){
       return withPhone(Operator.BETWEEN, startOfPhone, endOfPhone);
    }



    public BookstoreRequest<T> filterByCreateTime(LocalDateTime... createTime){
      if (createTime == null || createTime.length == 0) {
        throw new IllegalArgumentException("filterByCreateTime parameter createTime cannot be empty");
      }
      return appendSearchCriteria(createCreateTimeCriteria(Operator.EQUAL, (Object[])createTime));
    }

    public BookstoreRequest<T> withCreateTime(Operator operator, Object... values){
       return appendSearchCriteria(createCreateTimeCriteria(operator, values));
    }

    public BookstoreRequest<T> withCreateTimeIsUnknown(){
       return withCreateTime(Operator.IS_NULL);
    }

    public BookstoreRequest<T> withCreateTimeIsKnown(){
       return withCreateTime(Operator.IS_NOT_NULL);
    }

    public SearchCriteria createCreateTimeCriteria(Operator operator, Object... values) {
        return createBasicSearchCriteria(Bookstore.CREATE_TIME_PROPERTY, operator, values);
    }

    public BookstoreRequest<T> withCreateTimeGreaterThan(LocalDateTime createTime){
       return withCreateTime(Operator.GREATER_THAN, createTime);
    }

    public BookstoreRequest<T> withCreateTimeGreaterThanOrEqualTo(LocalDateTime createTime){
       return withCreateTime(Operator.GREATER_THAN_OR_EQUAL, createTime);
    }

    public BookstoreRequest<T> withCreateTimeLessThan(LocalDateTime createTime){
       return withCreateTime(Operator.LESS_THAN, createTime);
    }

    public BookstoreRequest<T> withCreateTimeLessThanOrEqualTo(LocalDateTime createTime){
       return withCreateTime(Operator.LESS_THAN_OR_EQUAL, createTime);
    }

    public BookstoreRequest<T> withCreateTimeBetween(LocalDateTime startOfCreateTime, LocalDateTime endOfCreateTime){
       return withCreateTime(Operator.BETWEEN, startOfCreateTime, endOfCreateTime);
    }
    public BookstoreRequest<T> withCreateTimeBefore(LocalDateTime createTime){
       return withCreateTime(Operator.LESS_THAN, createTime);
    }

    public BookstoreRequest<T> withCreateTimeBefore(Date createTime){
       return withCreateTime(Operator.LESS_THAN, createTime);
    }

    public BookstoreRequest<T> withCreateTimeAfter(LocalDateTime createTime){
       return withCreateTime(Operator.GREATER_THAN, createTime);
    }

    public BookstoreRequest<T> withCreateTimeAfter(Date createTime){
       return withCreateTime(Operator.GREATER_THAN, createTime);
    }

    public BookstoreRequest<T> withCreateTimeBetween(Date startOfCreateTime, Date endOfCreateTime){
       return withCreateTime(Operator.BETWEEN, startOfCreateTime, endOfCreateTime);
    }




    public BookstoreRequest<T> filterByUpdateTime(LocalDateTime... updateTime){
      if (updateTime == null || updateTime.length == 0) {
        throw new IllegalArgumentException("filterByUpdateTime parameter updateTime cannot be empty");
      }
      return appendSearchCriteria(createUpdateTimeCriteria(Operator.EQUAL, (Object[])updateTime));
    }

    public BookstoreRequest<T> withUpdateTime(Operator operator, Object... values){
       return appendSearchCriteria(createUpdateTimeCriteria(operator, values));
    }

    public BookstoreRequest<T> withUpdateTimeIsUnknown(){
       return withUpdateTime(Operator.IS_NULL);
    }

    public BookstoreRequest<T> withUpdateTimeIsKnown(){
       return withUpdateTime(Operator.IS_NOT_NULL);
    }

    public SearchCriteria createUpdateTimeCriteria(Operator operator, Object... values) {
        return createBasicSearchCriteria(Bookstore.UPDATE_TIME_PROPERTY, operator, values);
    }

    public BookstoreRequest<T> withUpdateTimeGreaterThan(LocalDateTime updateTime){
       return withUpdateTime(Operator.GREATER_THAN, updateTime);
    }

    public BookstoreRequest<T> withUpdateTimeGreaterThanOrEqualTo(LocalDateTime updateTime){
       return withUpdateTime(Operator.GREATER_THAN_OR_EQUAL, updateTime);
    }

    public BookstoreRequest<T> withUpdateTimeLessThan(LocalDateTime updateTime){
       return withUpdateTime(Operator.LESS_THAN, updateTime);
    }

    public BookstoreRequest<T> withUpdateTimeLessThanOrEqualTo(LocalDateTime updateTime){
       return withUpdateTime(Operator.LESS_THAN_OR_EQUAL, updateTime);
    }

    public BookstoreRequest<T> withUpdateTimeBetween(LocalDateTime startOfUpdateTime, LocalDateTime endOfUpdateTime){
       return withUpdateTime(Operator.BETWEEN, startOfUpdateTime, endOfUpdateTime);
    }
    public BookstoreRequest<T> withUpdateTimeBefore(LocalDateTime updateTime){
       return withUpdateTime(Operator.LESS_THAN, updateTime);
    }

    public BookstoreRequest<T> withUpdateTimeBefore(Date updateTime){
       return withUpdateTime(Operator.LESS_THAN, updateTime);
    }

    public BookstoreRequest<T> withUpdateTimeAfter(LocalDateTime updateTime){
       return withUpdateTime(Operator.GREATER_THAN, updateTime);
    }

    public BookstoreRequest<T> withUpdateTimeAfter(Date updateTime){
       return withUpdateTime(Operator.GREATER_THAN, updateTime);
    }

    public BookstoreRequest<T> withUpdateTimeBetween(Date startOfUpdateTime, Date endOfUpdateTime){
       return withUpdateTime(Operator.BETWEEN, startOfUpdateTime, endOfUpdateTime);
    }




    public BookstoreRequest<T> filterByVersion(Long... version){
      if (version == null || version.length == 0) {
        throw new IllegalArgumentException("filterByVersion parameter version cannot be empty");
      }
      return appendSearchCriteria(createVersionCriteria(Operator.EQUAL, (Object[])version));
    }

    public BookstoreRequest<T> withVersion(Operator operator, Object... values){
       return appendSearchCriteria(createVersionCriteria(operator, values));
    }

    public BookstoreRequest<T> withVersionIsUnknown(){
       return withVersion(Operator.IS_NULL);
    }

    public BookstoreRequest<T> withVersionIsKnown(){
       return withVersion(Operator.IS_NOT_NULL);
    }

    public SearchCriteria createVersionCriteria(Operator operator, Object... values) {
        return createBasicSearchCriteria(Bookstore.VERSION_PROPERTY, operator, values);
    }

    public BookstoreRequest<T> withVersionGreaterThan(Long version){
       return withVersion(Operator.GREATER_THAN, version);
    }

    public BookstoreRequest<T> withVersionGreaterThanOrEqualTo(Long version){
       return withVersion(Operator.GREATER_THAN_OR_EQUAL, version);
    }

    public BookstoreRequest<T> withVersionLessThan(Long version){
       return withVersion(Operator.LESS_THAN, version);
    }

    public BookstoreRequest<T> withVersionLessThanOrEqualTo(Long version){
       return withVersion(Operator.LESS_THAN_OR_EQUAL, version);
    }

    public BookstoreRequest<T> withVersionBetween(Long startOfVersion, Long endOfVersion){
       return withVersion(Operator.BETWEEN, startOfVersion, endOfVersion);
    }

    public BookstoreRequest<T> withBookListMatching(BookRequest bookRequest){
        return appendSearchCriteria(new SubQuerySearchCriteria(Bookstore.ID_PROPERTY, bookRequest, Book.BOOKSTORE_PROPERTY));
    }

    public BookstoreRequest<T> withoutBookListMatching(BookRequest bookRequest){
        return appendSearchCriteria(SearchCriteria.not(new SubQuerySearchCriteria(Bookstore.ID_PROPERTY, bookRequest, Book.BOOKSTORE_PROPERTY)));
    }

    public BookstoreRequest<T> haveBooks(){
        return withBookListMatching(Q.books().unlimited());
    }

    public BookstoreRequest<T> haveNoBooks(){
        return withoutBookListMatching(Q.books().unlimited());
    }
    public BookstoreRequest<T> withBookCategoryListMatching(BookCategoryRequest bookCategoryRequest){
        return appendSearchCriteria(new SubQuerySearchCriteria(Bookstore.ID_PROPERTY, bookCategoryRequest, BookCategory.BOOKSTORE_PROPERTY));
    }

    public BookstoreRequest<T> withoutBookCategoryListMatching(BookCategoryRequest bookCategoryRequest){
        return appendSearchCriteria(SearchCriteria.not(new SubQuerySearchCriteria(Bookstore.ID_PROPERTY, bookCategoryRequest, BookCategory.BOOKSTORE_PROPERTY)));
    }

    public BookstoreRequest<T> haveBookCategories(){
        return withBookCategoryListMatching(Q.bookCategories().unlimited());
    }

    public BookstoreRequest<T> haveNoBookCategories(){
        return withoutBookCategoryListMatching(Q.bookCategories().unlimited());
    }

    public BookstoreRequest<T> count(){
        super.count();
        return this;
    }
    public BookstoreRequest<T> countAs(String retName){
        super.count(retName);
        return this;
    }
    public BookstoreRequest minPhone(){
        return minPhoneAs(prefix("minOf",Bookstore.PHONE_PROPERTY));
    }

    public BookstoreRequest minPhoneAs(String retName){
        super.min(retName, Bookstore.PHONE_PROPERTY);
        return this;
    }
    public BookstoreRequest maxPhone(){
        return maxPhoneAs(prefix("maxOf",Bookstore.PHONE_PROPERTY));
    }

    public BookstoreRequest maxPhoneAs(String retName){
        super.max(retName, Bookstore.PHONE_PROPERTY);
        return this;
    }
    public BookstoreRequest sumPhone(){
        return sumPhoneAs(prefix("sumOf",Bookstore.PHONE_PROPERTY));
    }

    public BookstoreRequest sumPhoneAs(String retName){
        super.sum(retName, Bookstore.PHONE_PROPERTY);
        return this;
    }
    public BookstoreRequest avgPhone(){
        return avgPhoneAs(prefix("avgOf",Bookstore.PHONE_PROPERTY));
    }

    public BookstoreRequest avgPhoneAs(String retName){
        super.avg(retName, Bookstore.PHONE_PROPERTY);
        return this;
    }
    public BookstoreRequest standardDeviationPhone(){
        return standardDeviationPhoneAs(prefix("standardDeviationOf",Bookstore.PHONE_PROPERTY));
    }

    public BookstoreRequest standardDeviationPhoneAs(String retName){
        super.standardDeviation(retName, Bookstore.PHONE_PROPERTY);
        return this;
    }
    public BookstoreRequest squareRootOfPopulationStandardDeviationPhone(){
        return squareRootOfPopulationStandardDeviationPhoneAs(prefix("squareRootOfPopulationStandardDeviationOf",Bookstore.PHONE_PROPERTY));
    }

    public BookstoreRequest squareRootOfPopulationStandardDeviationPhoneAs(String retName){
        super.squareRootOfPopulationStandardDeviation(retName, Bookstore.PHONE_PROPERTY);
        return this;
    }
    public BookstoreRequest sampleVariancePhone(){
        return sampleVariancePhoneAs(prefix("sampleVarianceOf",Bookstore.PHONE_PROPERTY));
    }

    public BookstoreRequest sampleVariancePhoneAs(String retName){
        super.sampleVariance(retName, Bookstore.PHONE_PROPERTY);
        return this;
    }
    public BookstoreRequest samplePopulationVariancePhone(){
        return samplePopulationVariancePhoneAs(prefix("samplePopulationVarianceOf",Bookstore.PHONE_PROPERTY));
    }

    public BookstoreRequest samplePopulationVariancePhoneAs(String retName){
        super.samplePopulationVariance(retName, Bookstore.PHONE_PROPERTY);
        return this;
    }
    public BookstoreRequest<T> groupByBooksWithDetails(BookRequest subRequest){
       aggregate(Bookstore.BOOK_LIST_PROPERTY, subRequest);
       return this;
    }
    public BookstoreRequest<T> groupByBookCategoriesWithDetails(BookCategoryRequest subRequest){
       aggregate(Bookstore.BOOK_CATEGORY_LIST_PROPERTY, subRequest);
       return this;
    }

    public BookstoreRequest<T> groupById(){
       groupBy(Bookstore.ID_PROPERTY);
       return this;
    }

    public BookstoreRequest<T> groupByIdAs(String retName){
       groupBy(retName, Bookstore.ID_PROPERTY);
       return this;
    }

    public BookstoreRequest<T> groupByIdWithFunction(String retName, AggrFunction function){
       groupBy(retName, Bookstore.ID_PROPERTY, function);
       return this;
    }

    public BookstoreRequest<T> groupByName(){
       groupBy(Bookstore.NAME_PROPERTY);
       return this;
    }

    public BookstoreRequest<T> groupByNameAs(String retName){
       groupBy(retName, Bookstore.NAME_PROPERTY);
       return this;
    }

    public BookstoreRequest<T> groupByNameWithFunction(String retName, AggrFunction function){
       groupBy(retName, Bookstore.NAME_PROPERTY, function);
       return this;
    }

    public BookstoreRequest<T> groupByAddress(){
       groupBy(Bookstore.ADDRESS_PROPERTY);
       return this;
    }

    public BookstoreRequest<T> groupByAddressAs(String retName){
       groupBy(retName, Bookstore.ADDRESS_PROPERTY);
       return this;
    }

    public BookstoreRequest<T> groupByAddressWithFunction(String retName, AggrFunction function){
       groupBy(retName, Bookstore.ADDRESS_PROPERTY, function);
       return this;
    }

    public BookstoreRequest<T> groupByPhone(){
       groupBy(Bookstore.PHONE_PROPERTY);
       return this;
    }

    public BookstoreRequest<T> groupByPhoneAs(String retName){
       groupBy(retName, Bookstore.PHONE_PROPERTY);
       return this;
    }

    public BookstoreRequest<T> groupByPhoneWithFunction(String retName, AggrFunction function){
       groupBy(retName, Bookstore.PHONE_PROPERTY, function);
       return this;
    }

    public BookstoreRequest<T> groupByCreateTime(){
       groupBy(Bookstore.CREATE_TIME_PROPERTY);
       return this;
    }

    public BookstoreRequest<T> groupByCreateTimeAs(String retName){
       groupBy(retName, Bookstore.CREATE_TIME_PROPERTY);
       return this;
    }

    public BookstoreRequest<T> groupByCreateTimeWithFunction(String retName, AggrFunction function){
       groupBy(retName, Bookstore.CREATE_TIME_PROPERTY, function);
       return this;
    }

    public BookstoreRequest<T> groupByUpdateTime(){
       groupBy(Bookstore.UPDATE_TIME_PROPERTY);
       return this;
    }

    public BookstoreRequest<T> groupByUpdateTimeAs(String retName){
       groupBy(retName, Bookstore.UPDATE_TIME_PROPERTY);
       return this;
    }

    public BookstoreRequest<T> groupByUpdateTimeWithFunction(String retName, AggrFunction function){
       groupBy(retName, Bookstore.UPDATE_TIME_PROPERTY, function);
       return this;
    }

    public BookstoreRequest<T> groupByVersion(){
       groupBy(Bookstore.VERSION_PROPERTY);
       return this;
    }

    public BookstoreRequest<T> groupByVersionAs(String retName){
       groupBy(retName, Bookstore.VERSION_PROPERTY);
       return this;
    }

    public BookstoreRequest<T> groupByVersionWithFunction(String retName, AggrFunction function){
       groupBy(retName, Bookstore.VERSION_PROPERTY, function);
       return this;
    }



    public BookstoreRequest<T> orderByIdAscending(){
       addOrderByAscending(Bookstore.ID_PROPERTY);
       return this;
    }

    public BookstoreRequest<T> orderByIdDescending(){
       addOrderByDescending(Bookstore.ID_PROPERTY);
       return this;
    }

    public BookstoreRequest<T> orderByNameAscending(){
       addOrderByAscending(Bookstore.NAME_PROPERTY);
       return this;
    }

    public BookstoreRequest<T> orderByNameDescending(){
       addOrderByDescending(Bookstore.NAME_PROPERTY);
       return this;
    }
    public BookstoreRequest<T> orderByNameAscendingUsingGBK(){
       addOrderByAscendingUsingGBK(Bookstore.NAME_PROPERTY);
       return this;
    }

    public BookstoreRequest<T> orderByNameDescendingUsingGBK(){
       addOrderByDescendingUsingGBK(Bookstore.NAME_PROPERTY);
       return this;
    }
    public BookstoreRequest<T> orderByAddressAscending(){
       addOrderByAscending(Bookstore.ADDRESS_PROPERTY);
       return this;
    }

    public BookstoreRequest<T> orderByAddressDescending(){
       addOrderByDescending(Bookstore.ADDRESS_PROPERTY);
       return this;
    }
    public BookstoreRequest<T> orderByAddressAscendingUsingGBK(){
       addOrderByAscendingUsingGBK(Bookstore.ADDRESS_PROPERTY);
       return this;
    }

    public BookstoreRequest<T> orderByAddressDescendingUsingGBK(){
       addOrderByDescendingUsingGBK(Bookstore.ADDRESS_PROPERTY);
       return this;
    }
    public BookstoreRequest<T> orderByPhoneAscending(){
       addOrderByAscending(Bookstore.PHONE_PROPERTY);
       return this;
    }

    public BookstoreRequest<T> orderByPhoneDescending(){
       addOrderByDescending(Bookstore.PHONE_PROPERTY);
       return this;
    }

    public BookstoreRequest<T> orderByCreateTimeAscending(){
       addOrderByAscending(Bookstore.CREATE_TIME_PROPERTY);
       return this;
    }

    public BookstoreRequest<T> orderByCreateTimeDescending(){
       addOrderByDescending(Bookstore.CREATE_TIME_PROPERTY);
       return this;
    }

    public BookstoreRequest<T> orderByUpdateTimeAscending(){
       addOrderByAscending(Bookstore.UPDATE_TIME_PROPERTY);
       return this;
    }

    public BookstoreRequest<T> orderByUpdateTimeDescending(){
       addOrderByDescending(Bookstore.UPDATE_TIME_PROPERTY);
       return this;
    }

    public BookstoreRequest<T> orderByVersionAscending(){
       addOrderByAscending(Bookstore.VERSION_PROPERTY);
       return this;
    }

    public BookstoreRequest<T> orderByVersionDescending(){
       addOrderByDescending(Bookstore.VERSION_PROPERTY);
       return this;
    }


    public BookstoreRequest<T> statsFromBooksAs(String name, BookRequest subRequest){
       return statsFromBooksAs(name, subRequest, false);
    }

    public BookstoreRequest<T> statsFromBooksAs(String name, BookRequest subRequest, boolean singleResult){
       subRequest.setPartitionProperty(Book.BOOKSTORE_PROPERTY);
       addAggregateDynamicProperty(name, subRequest, singleResult);
       return this;
    }

    public BookstoreRequest<T> statsFromBooks(BookRequest subRequest){
       return statsFromBooksAs(REFINEMENTS, subRequest);
    }
    public BookstoreRequest<T> statsFromBookCategoriesAs(String name, BookCategoryRequest subRequest){
       return statsFromBookCategoriesAs(name, subRequest, false);
    }

    public BookstoreRequest<T> statsFromBookCategoriesAs(String name, BookCategoryRequest subRequest, boolean singleResult){
       subRequest.setPartitionProperty(BookCategory.BOOKSTORE_PROPERTY);
       addAggregateDynamicProperty(name, subRequest, singleResult);
       return this;
    }

    public BookstoreRequest<T> statsFromBookCategories(BookCategoryRequest subRequest){
       return statsFromBookCategoriesAs(REFINEMENTS, subRequest);
    }
    public BookstoreRequest<T> countBooks(){
        return countBooksAs("Count");
    }

    public BookstoreRequest<T> countBooksAs(String name){
        return countBooksWith(name, Q.books().unlimited());
    }

    public BookstoreRequest<T> countBooksWith(String name, BookRequest subRequest){
        return statsFromBooksAs(name, subRequest.count(), true);
    }
    public BookstoreRequest<T> countBookCategories(){
        return countBookCategoriesAs("Count");
    }

    public BookstoreRequest<T> countBookCategoriesAs(String name){
        return countBookCategoriesWith(name, Q.bookCategories().unlimited());
    }

    public BookstoreRequest<T> countBookCategoriesWith(String name, BookCategoryRequest subRequest){
        return statsFromBookCategoriesAs(name, subRequest.count(), true);
    }
    public BookstoreRequest<T> minPriceOfBooks(){
        return minPriceOfBooksAs("minPriceOfBooks");
    }

    public BookstoreRequest<T> minPriceOfBooksAs(String name){
        return minPriceOfBooksAs(name, Q.books().unlimited());
    }

    public BookstoreRequest<T> minPriceOfBooksAs(String name, BookRequest subRequest){
        return statsFromBooksAs(name, subRequest.minPrice(), true);
    }
    public BookstoreRequest<T> maxPriceOfBooks(){
        return maxPriceOfBooksAs("maxPriceOfBooks");
    }

    public BookstoreRequest<T> maxPriceOfBooksAs(String name){
        return maxPriceOfBooksAs(name, Q.books().unlimited());
    }

    public BookstoreRequest<T> maxPriceOfBooksAs(String name, BookRequest subRequest){
        return statsFromBooksAs(name, subRequest.maxPrice(), true);
    }
    public BookstoreRequest<T> sumPriceOfBooks(){
        return sumPriceOfBooksAs("sumPriceOfBooks");
    }

    public BookstoreRequest<T> sumPriceOfBooksAs(String name){
        return sumPriceOfBooksAs(name, Q.books().unlimited());
    }

    public BookstoreRequest<T> sumPriceOfBooksAs(String name, BookRequest subRequest){
        return statsFromBooksAs(name, subRequest.sumPrice(), true);
    }
    public BookstoreRequest<T> avgPriceOfBooks(){
        return avgPriceOfBooksAs("avgPriceOfBooks");
    }

    public BookstoreRequest<T> avgPriceOfBooksAs(String name){
        return avgPriceOfBooksAs(name, Q.books().unlimited());
    }

    public BookstoreRequest<T> avgPriceOfBooksAs(String name, BookRequest subRequest){
        return statsFromBooksAs(name, subRequest.avgPrice(), true);
    }
    public BookstoreRequest<T> standardDeviationPriceOfBooks(){
        return standardDeviationPriceOfBooksAs("stdDevPriceOfBooks");
    }

    public BookstoreRequest<T> standardDeviationPriceOfBooksAs(String name){
        return standardDeviationPriceOfBooksAs(name, Q.books().unlimited());
    }

    public BookstoreRequest<T> standardDeviationPriceOfBooksAs(String name, BookRequest subRequest){
        return statsFromBooksAs(name, subRequest.standardDeviationPrice(), true);
    }
    public BookstoreRequest<T> squareRootOfPopulationStandardDeviationPriceOfBooks(){
        return squareRootOfPopulationStandardDeviationPriceOfBooksAs("stdDevPopPriceOfBooks");
    }

    public BookstoreRequest<T> squareRootOfPopulationStandardDeviationPriceOfBooksAs(String name){
        return squareRootOfPopulationStandardDeviationPriceOfBooksAs(name, Q.books().unlimited());
    }

    public BookstoreRequest<T> squareRootOfPopulationStandardDeviationPriceOfBooksAs(String name, BookRequest subRequest){
        return statsFromBooksAs(name, subRequest.squareRootOfPopulationStandardDeviationPrice(), true);
    }
    public BookstoreRequest<T> sampleVariancePriceOfBooks(){
        return sampleVariancePriceOfBooksAs("varSampPriceOfBooks");
    }

    public BookstoreRequest<T> sampleVariancePriceOfBooksAs(String name){
        return sampleVariancePriceOfBooksAs(name, Q.books().unlimited());
    }

    public BookstoreRequest<T> sampleVariancePriceOfBooksAs(String name, BookRequest subRequest){
        return statsFromBooksAs(name, subRequest.sampleVariancePrice(), true);
    }
    public BookstoreRequest<T> samplePopulationVariancePriceOfBooks(){
        return samplePopulationVariancePriceOfBooksAs("varPopPriceOfBooks");
    }

    public BookstoreRequest<T> samplePopulationVariancePriceOfBooksAs(String name){
        return samplePopulationVariancePriceOfBooksAs(name, Q.books().unlimited());
    }

    public BookstoreRequest<T> samplePopulationVariancePriceOfBooksAs(String name, BookRequest subRequest){
        return statsFromBooksAs(name, subRequest.samplePopulationVariancePrice(), true);
    }
    public BookstoreRequest<T> minStockCountOfBooks(){
        return minStockCountOfBooksAs("minStockCountOfBooks");
    }

    public BookstoreRequest<T> minStockCountOfBooksAs(String name){
        return minStockCountOfBooksAs(name, Q.books().unlimited());
    }

    public BookstoreRequest<T> minStockCountOfBooksAs(String name, BookRequest subRequest){
        return statsFromBooksAs(name, subRequest.minStockCount(), true);
    }
    public BookstoreRequest<T> maxStockCountOfBooks(){
        return maxStockCountOfBooksAs("maxStockCountOfBooks");
    }

    public BookstoreRequest<T> maxStockCountOfBooksAs(String name){
        return maxStockCountOfBooksAs(name, Q.books().unlimited());
    }

    public BookstoreRequest<T> maxStockCountOfBooksAs(String name, BookRequest subRequest){
        return statsFromBooksAs(name, subRequest.maxStockCount(), true);
    }
    public BookstoreRequest<T> sumStockCountOfBooks(){
        return sumStockCountOfBooksAs("sumStockCountOfBooks");
    }

    public BookstoreRequest<T> sumStockCountOfBooksAs(String name){
        return sumStockCountOfBooksAs(name, Q.books().unlimited());
    }

    public BookstoreRequest<T> sumStockCountOfBooksAs(String name, BookRequest subRequest){
        return statsFromBooksAs(name, subRequest.sumStockCount(), true);
    }
    public BookstoreRequest<T> avgStockCountOfBooks(){
        return avgStockCountOfBooksAs("avgStockCountOfBooks");
    }

    public BookstoreRequest<T> avgStockCountOfBooksAs(String name){
        return avgStockCountOfBooksAs(name, Q.books().unlimited());
    }

    public BookstoreRequest<T> avgStockCountOfBooksAs(String name, BookRequest subRequest){
        return statsFromBooksAs(name, subRequest.avgStockCount(), true);
    }
    public BookstoreRequest<T> standardDeviationStockCountOfBooks(){
        return standardDeviationStockCountOfBooksAs("stdDevStockCountOfBooks");
    }

    public BookstoreRequest<T> standardDeviationStockCountOfBooksAs(String name){
        return standardDeviationStockCountOfBooksAs(name, Q.books().unlimited());
    }

    public BookstoreRequest<T> standardDeviationStockCountOfBooksAs(String name, BookRequest subRequest){
        return statsFromBooksAs(name, subRequest.standardDeviationStockCount(), true);
    }
    public BookstoreRequest<T> squareRootOfPopulationStandardDeviationStockCountOfBooks(){
        return squareRootOfPopulationStandardDeviationStockCountOfBooksAs("stdDevPopStockCountOfBooks");
    }

    public BookstoreRequest<T> squareRootOfPopulationStandardDeviationStockCountOfBooksAs(String name){
        return squareRootOfPopulationStandardDeviationStockCountOfBooksAs(name, Q.books().unlimited());
    }

    public BookstoreRequest<T> squareRootOfPopulationStandardDeviationStockCountOfBooksAs(String name, BookRequest subRequest){
        return statsFromBooksAs(name, subRequest.squareRootOfPopulationStandardDeviationStockCount(), true);
    }
    public BookstoreRequest<T> sampleVarianceStockCountOfBooks(){
        return sampleVarianceStockCountOfBooksAs("varSampStockCountOfBooks");
    }

    public BookstoreRequest<T> sampleVarianceStockCountOfBooksAs(String name){
        return sampleVarianceStockCountOfBooksAs(name, Q.books().unlimited());
    }

    public BookstoreRequest<T> sampleVarianceStockCountOfBooksAs(String name, BookRequest subRequest){
        return statsFromBooksAs(name, subRequest.sampleVarianceStockCount(), true);
    }
    public BookstoreRequest<T> samplePopulationVarianceStockCountOfBooks(){
        return samplePopulationVarianceStockCountOfBooksAs("varPopStockCountOfBooks");
    }

    public BookstoreRequest<T> samplePopulationVarianceStockCountOfBooksAs(String name){
        return samplePopulationVarianceStockCountOfBooksAs(name, Q.books().unlimited());
    }

    public BookstoreRequest<T> samplePopulationVarianceStockCountOfBooksAs(String name, BookRequest subRequest){
        return statsFromBooksAs(name, subRequest.samplePopulationVarianceStockCount(), true);
    }



    /**
     * get topN records
     * @param topN  records number
     */
    public BookstoreRequest<T> top(int topN) {
        super.top(topN);
        return this;
    }

    /**
     * get records from offset(inclusive) to offset+size(exclusive)
     * @param offset record offset
     * @param size records number
     */
    public BookstoreRequest<T> offset(int offset, int size) {
        super.offset(offset, size);
        return this;
    }

    /**
     * retrieve all records
     */
    public BookstoreRequest<T> unlimited() {
        super.unlimited();
        return this;
    }

    /**
     * get records of one page
     * @param pageNumber page number(1-based)
     * @param pageSize page size
     */
    public BookstoreRequest<T> page(int pageNumber, int pageSize) {
        int offset = (pageNumber - 1) * pageSize;
        return offset(offset, pageSize);
   }

    /**
     * get records of one page, default page size is 10
     * @param pageNumber page number(1-based)
     */
    public BookstoreRequest<T> page(int pageNumber) {
        return page(pageNumber, 10);
   }
}