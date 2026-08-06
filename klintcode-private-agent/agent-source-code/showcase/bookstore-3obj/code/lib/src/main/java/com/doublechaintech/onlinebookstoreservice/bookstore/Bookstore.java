package com.doublechaintech.onlinebookstoreservice.bookstore;

import com.doublechaintech.onlinebookstoreservice.book.Book;
import com.doublechaintech.onlinebookstoreservice.bookcategory.BookCategory;
import io.teaql.core.Audited;
import io.teaql.core.BaseEntity;
import io.teaql.core.EntityStatus;
import io.teaql.core.FrameworkInternal;
import io.teaql.core.RemoteInput;
import io.teaql.core.SmartList;
import java.time.LocalDateTime;
import java.util.Objects;

/**
 * [TEAQL AI WARNING]
 * TeaQL was explicitly designed to PREVENT AI hallucinations and random guessing.
 * DO NOT GUESS METHOD NAMES!
 * The methods listed below are the ONLY valid ways to interact with this entity.
 * If you encounter compilation errors (e.g., method not found), DO NOT guess another method name.
 * Read the method signatures in this file before proceeding.
 */
public class Bookstore extends BaseEntity implements RemoteInput {
    public static String INTERNAL_TYPE = "Bookstore";

    public static final String NAME_PROPERTY = "name";
    public static final String ADDRESS_PROPERTY = "address";
    public static final String PHONE_PROPERTY = "phone";
    public static final String CREATE_TIME_PROPERTY = "createTime";
    public static final String UPDATE_TIME_PROPERTY = "updateTime";
    public static final String BOOK_LIST_PROPERTY = "bookList";
    public static final String BOOK_CATEGORY_LIST_PROPERTY = "bookCategoryList";
    private String name;
    private String address;
    private Integer phone;
    private LocalDateTime createTime;
    private LocalDateTime updateTime;
    private SmartList<Book> bookList;
    private SmartList<BookCategory> bookCategoryList;

    public String getName(){
        return this.name;
    }
    public String getAddress(){
        return this.address;
    }
    public Integer getPhone(){
        return this.phone;
    }
    public LocalDateTime getCreateTime(){
        return this.createTime;
    }
    public LocalDateTime getUpdateTime(){
        return this.updateTime;
    }
    public SmartList<Book> getBookList(){
        return this.bookList;
    }
    public SmartList<BookCategory> getBookCategoryList(){
        return this.bookCategoryList;
    }
    public Bookstore updateName(String name){
        name = (name == null ? null : name.trim());
        if(Objects.equals(this.name, name)){
            return this;
        }
        handleUpdate(NAME_PROPERTY, getName(), name);
        this.name = name;
        return this;
    }
    public Bookstore updateAddress(String address){
        address = (address == null ? null : address.trim());
        if(Objects.equals(this.address, address)){
            return this;
        }
        handleUpdate(ADDRESS_PROPERTY, getAddress(), address);
        this.address = address;
        return this;
    }
    public Bookstore updatePhone(Integer phone){
        if(Objects.equals(this.phone, phone)){
            return this;
        }
        handleUpdate(PHONE_PROPERTY, getPhone(), phone);
        this.phone = phone;
        return this;
    }
    public Bookstore updateCreateTime(LocalDateTime createTime){
        if(Objects.equals(this.createTime, createTime)){
            return this;
        }
        handleUpdate(CREATE_TIME_PROPERTY, getCreateTime(), createTime);
        this.createTime = createTime;
        return this;
    }
    public Bookstore updateUpdateTime(LocalDateTime updateTime){
        if(Objects.equals(this.updateTime, updateTime)){
            return this;
        }
        handleUpdate(UPDATE_TIME_PROPERTY, getUpdateTime(), updateTime);
        this.updateTime = updateTime;
        return this;
    }
    public Bookstore addBook(Book book){
        if (book == null){
            return this;
        }

        if(null == this.bookList){
            this.bookList = new SmartList<>();
        }

        this.bookList.add(book);
        book.cacheRelation(Book.BOOKSTORE_PROPERTY, this);
        return this;
    }
    public Bookstore addBookCategory(BookCategory bookCategory){
        if (bookCategory == null){
            return this;
        }

        if(null == this.bookCategoryList){
            this.bookCategoryList = new SmartList<>();
        }

        this.bookCategoryList.add(bookCategory);
        bookCategory.cacheRelation(BookCategory.BOOKSTORE_PROPERTY, this);
        return this;
    }

    public static Bookstore refer(Long id){
        Bookstore refer = new Bookstore();
        refer.__internalSet("id", id);
        refer.set$status(EntityStatus.REFER);
        return refer;
    }
    @Override
    public String typeName(){
        return INTERNAL_TYPE;
    }

    public Bookstore comment(String comment){
        this.setComment(comment);
        return this;
    }

    @Override
    @SuppressWarnings("unchecked")
    public Audited<Bookstore> auditAs(String action) {
        return super.auditAs(action);
    }

    // ===== Framework Internal: generated switch dispatch =====
    @Override
    @FrameworkInternal
    public void __internalSet(String property, Object value) {
        switch (property) {
            case "name": this.name = (value == null ? null : ((String)value).trim()); break;

            case "address": this.address = (value == null ? null : ((String)value).trim()); break;

            case "phone": this.phone = (Integer) value; break;

            case "createTime": this.createTime = (LocalDateTime) value; break;

            case "updateTime": this.updateTime = (LocalDateTime) value; break;

            case "bookList": this.bookList = (SmartList<Book>) value; break;
            case "bookCategoryList": this.bookCategoryList = (SmartList<BookCategory>) value; break;
            default: super.__internalSet(property, value);
        }
    }

    @Override
    @FrameworkInternal
    public Object __internalGet(String property) {
        switch (property) {
            case "name": return this.name;
            case "address": return this.address;
            case "phone": return this.phone;
            case "createTime": return this.createTime;
            case "updateTime": return this.updateTime;
            case "bookList": return this.bookList;
            case "bookCategoryList": return this.bookCategoryList;
            default: return super.__internalGet(property);
        }
    }

}